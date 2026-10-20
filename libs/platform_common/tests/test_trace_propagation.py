from opentelemetry import propagate, trace

from platform_common.observability import configure_aws_propagation


def test_gateway_parent_and_w3c_fallback_are_preserved():
    previous = propagate.get_global_textmap()
    try:
        configure_aws_propagation()
        trace_id = '675000001234567890abcdef12345678'
        parent = '0123456789abcdef'
        gateway = {'X-Amzn-Trace-Id': f'Root=1-{trace_id[:8]}-{trace_id[8:]};Parent={parent};Sampled=1'}
        context = propagate.extract(gateway)
        span = trace.get_current_span(context).get_span_context()
        assert span.trace_id == int(trace_id, 16)
        assert span.span_id == int(parent, 16)
        assert span.trace_flags.sampled
        carrier = {}
        propagate.inject(carrier, context=context)
        assert carrier['traceparent'] == f'00-{trace_id}-{parent}-01'
        assert 'Root=1-' + trace_id[:8] + '-' + trace_id[8:] in carrier['X-Amzn-Trace-Id']

        fallback = propagate.extract({'traceparent': f'00-{trace_id}-{parent}-01'})
        assert trace.get_current_span(fallback).get_span_context().trace_id == int(trace_id, 16)
        # When both contexts are present, continue the gateway's parent.
        both = {**gateway, 'traceparent': '00-' + '1' * 32 + '-' + '2' * 16 + '-01'}
        assert trace.get_current_span(propagate.extract(both)).get_span_context().span_id == int(parent, 16)
    finally:
        propagate.set_global_textmap(previous)
