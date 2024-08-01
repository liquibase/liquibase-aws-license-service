# Use the official Liquibase image as the base
FROM liquibase/liquibase:4.29.1

# Add the AWS License Service Extension using the Liquibase Package Manager (LPM)
RUN lpm update && lpm add liquibase-aws-license-service

# Default command to display Liquibase version
CMD ["liquibase", "--version"]