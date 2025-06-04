FROM nginx:alpine

# Copy static files to nginx html directory
COPY . /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Nginx runs in the foreground by default 