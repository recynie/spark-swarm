FROM alpine:latest
CMD mkdir -p /output && echo "runtime artifact" > /output/result.txt && echo '{"status":"ok"}' > /output/metadata.json
