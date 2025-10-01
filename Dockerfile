FROM liquibase/liquibase-secure:5.0.0 AS builder

ARG LPM_VERSION=0.2.14
ARG LPM_SHA256=28750d84bf76d32ba3a2d51674a1b4e14205523c87e4655b2cd8de68b916758e
ARG LPM_SHA256_ARM=541a220aa3c3227cc0fb40b15976b11011568a06a6499af090258bf604f45cc0

# Download and Install lpm
RUN apt-get update && \
    apt-get -yqq install unzip --no-install-recommends && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /liquibase/bin && \
    arch="$(dpkg --print-architecture)" && \
    if [ "$arch" = "amd64" ]; then \
        DOWNLOAD_ARCH=""; \
        DOWNLOAD_SHA256="$LPM_SHA256"; \
    elif [ "$arch" = "arm64" ]; then \
        DOWNLOAD_ARCH="-arm64"; \
        DOWNLOAD_SHA256="$LPM_SHA256_ARM"; \
    else \
        echo >&2 "error: unsupported architecture '$arch'"; \
        exit 1; \
    fi && \
    wget -q -O /tmp/lpm-${LPM_VERSION}-linux${DOWNLOAD_ARCH}.zip "https://github.com/liquibase/liquibase-package-manager/releases/download/v${LPM_VERSION}/lpm-${LPM_VERSION}-linux${DOWNLOAD_ARCH}.zip" && \
    echo "$DOWNLOAD_SHA256 */tmp/lpm-${LPM_VERSION}-linux${DOWNLOAD_ARCH}.zip" | sha256sum -c - && \
    unzip /tmp/lpm-${LPM_VERSION}-linux${DOWNLOAD_ARCH}.zip -d /liquibase/bin/ && \
    rm /tmp/lpm-${LPM_VERSION}-linux${DOWNLOAD_ARCH}.zip && \
    apt-get purge -y --auto-remove unzip && \
    ln -s /liquibase/bin/lpm /usr/local/bin/lpm && \
    lpm --version

# Marker which indicates this is a Liquibase docker container
ENV DOCKER_AWS_LIQUIBASE=true

# Add support for Liquibase PRO extensions using the Liquibase Package Manager (LPM)
RUN lpm update && \
    lpm add \
    liquibase-aws-license-service \
    --global

# Final stage - clean image without LPM
FROM liquibase/liquibase-secure:5.0.0

# Marker which indicates this is a Liquibase docker container
ENV DOCKER_AWS_LIQUIBASE=true

# Copy only the installed extension JAR files from builder stage
COPY --from=builder /liquibase/liquibase_libs/*.jar /liquibase/lib/

# Default command to display Liquibase version
CMD ["liquibase", "--help"]