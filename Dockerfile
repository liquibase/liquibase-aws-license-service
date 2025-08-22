# Build stage - install extension using LPM
FROM liquibase/liquibase-secure:4.33.0 AS builder

RUN lpm --download=true --lpmHome=/opt/lpm add liquibase-aws-license-service

# Final stage - clean image without LPM
FROM liquibase/liquibase-secure:4.33.0

ENV DOCKER_AWS_LIQUIBASE=true

# Copy the installed extension from builder stage
COPY --from=builder /liquibase/lib /liquibase/lib

# Default command to display Liquibase version
CMD ["liquibase", "--help"]
