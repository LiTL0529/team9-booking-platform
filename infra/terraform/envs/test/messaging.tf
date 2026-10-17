# Event bus: one SNS topic per publishing service, one SQS queue (with a DLQ) per subscribing
# service. Same topology as local/messaging/bootstrap.py.

locals {
  topics = toset(["merchant-events", "catalogue-events", "booking-events"])
  queues = {
    "availability-events" = ["merchant-events", "catalogue-events", "booking-events"]
    "booking-slot-events" = ["catalogue-events"]
    "notification-events" = ["booking-events"]
  }
  subscriptions = merge([
    for queue, topics in local.queues : { for topic in topics : "${queue}:${topic}" => { queue = queue, topic = topic } }
  ]...)
}

resource "aws_sns_topic" "events" {
  for_each          = local.topics
  name              = "${local.name}-${each.key}"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sqs_queue" "dlq" {
  for_each                  = local.queues
  name                      = "${local.name}-${each.key}-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "events" {
  for_each                   = local.queues
  name                       = "${local.name}-${each.key}"
  visibility_timeout_seconds = 30
  receive_wait_time_seconds  = 20
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = 5
  })
}

data "aws_iam_policy_document" "queue" {
  for_each = local.queues
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.events[each.key].arn]
    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [for t in each.value : aws_sns_topic.events[t].arn]
    }
  }
}

resource "aws_sqs_queue_policy" "events" {
  for_each  = local.queues
  queue_url = aws_sqs_queue.events[each.key].id
  policy    = data.aws_iam_policy_document.queue[each.key].json
}

resource "aws_sns_topic_subscription" "events" {
  for_each             = local.subscriptions
  topic_arn            = aws_sns_topic.events[each.value.topic].arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.events[each.value.queue].arn
  raw_message_delivery = true
}
