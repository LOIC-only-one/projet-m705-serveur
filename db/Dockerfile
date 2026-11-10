FROM mongo:8.2

COPY docker-entrypoint-production.sh /usr/local/bin/docker-entrypoint-production.sh
RUN chmod 0555 /usr/local/bin/docker-entrypoint-production.sh

ENTRYPOINT ["docker-entrypoint-production.sh"]
CMD ["mongod"]
