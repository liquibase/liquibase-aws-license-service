FROM liquibase/liquibase-secure:4.33.0 AS builder

ARG LPM_VERSION=0.2.11
ARG LPM_SHA256=d07d1373446d2a9f11010649d705eba2ebefc23aedffec58d4d0a117c9a195b7
ARG LPM_SHA256_ARM=77c8cf8369ad07ed536c3b4c352e40815f32f89b111cafabf8e3cfc102d912f8

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
FROM liquibase/liquibase-secure:4.33.0

# Marker which indicates this is a Liquibase docker container
ENV DOCKER_AWS_LIQUIBASE=true

# Copy only the installed extension JAR files from builder stage
COPY --from=builder /liquibase/liquibase_libs/*.jar /liquibase/lib/

# Default command to display Liquibase version
CMD ["liquibase", "--help"]