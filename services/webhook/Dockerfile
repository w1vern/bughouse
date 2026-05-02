FROM alpine:3.20

RUN apk add --no-cache webhook docker-cli docker-cli-compose

EXPOSE 9000

ENTRYPOINT ["webhook"]
CMD ["-hooks=/etc/webhook/hooks.yaml", "-template", "-verbose", "-port=9000"]
