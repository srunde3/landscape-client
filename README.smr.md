# Debian hash package reporting

## Test locally

Configure your `landscape-client.conf` to point to your server dev environment.

```
sudo -u landscape ./scripts/landscape-client -c landscape-client.conf
```

## Test in an installation

1. Make a client build with `make quick-build`.
2. Install in a container
3. Optionally, attach a pro token now
4. Publish your container image

See the cpu-profiling repo for next steps.