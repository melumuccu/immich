# immich

## Docker Compose setup for Mac Studio hybrid storage

This repository includes a minimal Docker Compose setup for running Immich with:

- the **internal SSD** storing PostgreSQL data, thumbnails, profile data, encoded video cache, and ML cache
- the **external HDD** storing the original photo/video library

### Files

- `.env`: environment variables and host-side mount paths
- `docker-compose.yml`: a hybrid mount layout that keeps hot data on the SSD and large library data on the external drive

### Validate the configuration

```bash
docker compose config
```

If you use a different macOS username or volume name, update the paths in `.env` first.
