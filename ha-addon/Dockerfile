ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /app
COPY server/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY server/ .
COPY VERSION /app/VERSION

# Bundle local build client (runs alongside the server to ensure a client is always available)
COPY client/ /app/client/

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
