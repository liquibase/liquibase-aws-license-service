# Stage 1: Download LPM using a minimal base image with root access
FROM ubuntu:jammy AS downloader

ARG LPM_VERSION=0.2.14
ARG LPM_SHA256=28750d84bf76d32ba3a2d51674a1b4e14205523c87e4655b2cd8de68b916758e
ARG LPM_SHA256_ARM=541a220aa3c3227cc0fb40b15976b11011568a06a6499af090258bf604f45cc0

# Download and verify LPM
RUN apt-get update && \
    apt-get install -y wget unzip ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
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
    wget -q -O /tmp/lpm.zip "https://github.com/liquibase/liquibase-package-manager/releases/download/v${LPM_VERSION}/lpm-${LPM_VERSION}-linux${DOWNLOAD_ARCH}.zip" && \
    echo "$DOWNLOAD_SHA256 */tmp/lpm.zip" | sha256sum -c - && \
    mkdir -p /opt/lpm && \
    unzip /tmp/lpm.zip -d /opt/lpm && \
    chmod +x /opt/lpm/lpm

# Stage 2: Use LPM with Liquibase Secure to install extensions (no root needed)
FROM liquibase/liquibase-secure:5.0.0 AS builder

# Copy LPM from downloader stage with proper ownership
COPY --from=downloader --chown=liquibase:liquibase /opt/lpm/lpm /usr/local/bin/lpm

# Marker which indicates this is a Liquibase docker container
ENV DOCKER_AWS_LIQUIBASE=true

# Add support for Liquibase SECURE extensions using the Liquibase Package Manager (LPM)
RUN lpm update && \
    lpm add liquibase-aws-license-service --global

# Stage 3: Final clean image without LPM
FROM liquibase/liquibase-secure:5.0.0

# Marker which indicates this is a Liquibase docker container
ENV DOCKER_AWS_LIQUIBASE=true

# Copy only the installed extension JAR files from builder stage
COPY --from=builder /liquibase/lib/*.jar /liquibase/lib/

# Default command to display Liquibase version
CMD ["liquibase", "--help"]