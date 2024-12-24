# Troubleshooting Common Issues

Taking care of the server is essential to keep apps running smoothly. Monitor the server's health and take action when necessary. The best way to monitor is to use the Digital Ocean dashboard. Here are some previous issues and steps to resolve them.

### CPU Usage Spikes

If CPU usage is high, you can check the top processes by running `top` or `htop` and try to kill a long-running process or query. Sometimes the quickest fix is to restart the server.

### Rebooting

When rebooting the server on digital ocean, everything should be running fine. If for some reason app.regendata.xyz is not loading, try the following steps:

1. Log into the console from the digital ocean dashboard.
2. Check the nginx status by running `sudo systemctl status nginx`.
3. If the status is inactive, run `sudo systemctl start nginx`.
4. Ensure nginx starts on boot by running `sudo systemctl enable nginx`. You can check what it's currently set to by running `sudo systemctl is-enabled nginx`.

Nginx should now be running and the app should be accessible at app.regendata.xyz. If it's still not working, try rebooting the server by running `sudo reboot` and then check the status of nginx again. Nginx is a reverse proxy server that forwards requests to the app.

### Disk Usage Maxing

Sometimes the disk usage appears to be getting full due to various reasons. This is usually related to Docker logs.
To check your overall disk usage, run the following command:
```
df -h
```
This command provides a summary of disk space usage for each filesystem, showing the total size, used space, available space, and usage percentage. Look for the main filesystem (e.g., `/dev/vda1`) to assess overall disk usage.

To truncate/trim/clear Docker logs, run the following commands in the droplet console.

First, find the container name by running 
```
docker ps
```

Then, run the following command to clear the logs:
```
truncate -s 0 $(docker inspect --format='{{.LogPath}}' <container_name>)
```
Replace `<container_name>` with the actual container name you found in the first step. For example, if the container name is `grantsdb`, you would run:
```
truncate -s 0 $(docker inspect --format='{{.LogPath}}' grantsdb)
```
To verify the logs are cleared, run `df -h` again and check the percentage of used space. If it's still high, you may need to clear more logs or investigate other disk usage issues.