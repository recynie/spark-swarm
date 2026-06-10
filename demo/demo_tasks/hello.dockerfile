FROM alpine:latest
RUN echo "Hello from Spark-Swarm!"
RUN echo "Build completed at $(date)"
CMD echo "Container is running..." && sleep 2 && echo "Task finished successfully!"
