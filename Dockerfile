# Use the official Liquibase image as the base
FROM liquibase/liquibase:4.29.2

# Marker which indicates this is a Liquibase docker container
ENV DOCKER_AWS_LIQUIBASE=true

# Add the AWS License Service and other extensions using the Liquibase Package Manager (LPM)
RUN lpm update && \
    lpm add liquibase-aws-license-service liquibase-s3-extension liquibase-aws-secrets-manager \
            liquibase-commercial-mongodb liquibase-commercial-dynamodb liquibase-checks --global


# Default command to display Liquibase version
CMD ["liquibase", "--help"]
