FROM python:3.10-slim

WORKDIR /app

# Install git (required for git operations)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . /app

# Install the package
RUN pip install --no-cache-dir .

# Verify installation
RUN release-tool -h

CMD ["release-tool"]
