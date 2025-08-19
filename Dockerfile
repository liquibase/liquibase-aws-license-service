# Use the official Liquibase-PRO image as the base
FROM liquibase/liquibase-pro:4.33.0


# Add support for Liquibase PRO extensions using the Liquibase Package Manager (LPM)
RUN lpm update && \
    lpm add \
    liquibase-aws-license-service \
    liquibase-aws-extension \
    --global


# Default command to display Liquibase version
CMD ["liquibase", "--help"]
