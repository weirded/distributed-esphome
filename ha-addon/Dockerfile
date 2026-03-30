ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /app
COPY server/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY server/ .
COPY VERSION /app/VERSION

# Bundle client code so the server can serve it to remote clients for auto-update
COPY client/ /app/client/

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
