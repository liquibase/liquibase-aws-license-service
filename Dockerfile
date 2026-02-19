FROM liquibase/liquibase-secure:5.1.0

# Marker which indicates this is a Liquibase docker container
ENV DOCKER_AWS_LIQUIBASE=true

# Install the AWS license service extension using LPM
RUN lpm update && \
    lpm add liquibase-aws-license-service --global

# Default command to display Liquibase version
CMD ["liquibase", "--help"]
