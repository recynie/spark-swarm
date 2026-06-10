FROM alpine:latest
RUN echo "Creating output files..."
RUN mkdir -p /output
RUN echo "This is the output content" > /output/result.txt
RUN echo '{"key": "value", "status": "ok"}' > /output/data.json
RUN echo "Log line 1" && sleep 1 && echo "Log line 2" && sleep 1 && echo "Log line 3"
CMD echo "Processing complete"
