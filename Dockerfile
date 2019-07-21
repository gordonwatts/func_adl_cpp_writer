# Build image that has all the software to convert AST's to C++ code

# Based on a python3 - latest.
FROM python:3

WORKDIR /usr/src/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Get over the source code
COPY tools/ .

# Turn this on so that stdout isn't buffered - otherwise logs in kubectl don't
# show up until much later!
ENV PYTHONUNBUFFERED=1

CMD ["/bin/bash"]
