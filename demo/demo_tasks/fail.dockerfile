FROM alpine:latest
RUN this-command-does-not-exist
CMD echo "This should never run"
