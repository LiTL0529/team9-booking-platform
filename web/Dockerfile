# Local stand-in for CloudFront + S3: nginx serves the built app and forwards API calls
# to the gateway on the same origin (CloudFront does the same with an /v1/* behaviour).
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
