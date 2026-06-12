FROM alpine:3.22

ENV TZ=Asia/Tokyo \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apk add --no-cache \
      bash \
      ca-certificates \
      rclone \
      tzdata \
    && cp /usr/share/zoneinfo/Asia/Tokyo /etc/localtime \
    && echo "Asia/Tokyo" > /etc/timezone \
    && mkdir -p /app \
    && printf '%s\n' \
      'SHELL=/bin/bash' \
      'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
      'TZ=Asia/Tokyo' \
      '30 2 * * * source /etc/container.env && /app/backup.sh >> /proc/1/fd/1 2>> /proc/1/fd/2' \
      > /etc/crontabs/root

COPY backup.sh /app/backup.sh

RUN chmod +x /app/backup.sh

CMD ["bash", "-lc", "umask 077; export -p > /etc/container.env; exec crond -f -l 8 -L /proc/1/fd/1"]
