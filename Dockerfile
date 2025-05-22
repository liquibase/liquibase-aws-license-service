# Use the official Liquibase image as the base
FROM liquibase/liquibase:4.32.0

# Marker which indicates this is a Liquibase docker container
ENV DOCKER_AWS_LIQUIBASE=true

# Add support for Liquibase PRO extensions using the Liquibase Package Manager (LPM)
RUN lpm update && \
    lpm add \
    liquibase-aws-license-service \
    liquibase-aws-extension \
    --global


# Default command to display Liquibase version
CMD ["liquibase", "--help"]
