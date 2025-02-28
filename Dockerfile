FROM python:3.9-slim

# Install Poetry
RUN pip install poetry

# Set the working directory
WORKDIR /app

# Copy the pyproject.toml file
COPY pyproject.toml ./

# Install the dependencies
RUN poetry install --no-root

# Copy the Flask app
COPY pr-service.py .

# Expose the port the app runs on
EXPOSE 5000

# Run the Flask app
CMD ["poetry", "run", "python", "pr-service.py"]