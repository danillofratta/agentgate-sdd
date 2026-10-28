FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html
COPY src/app.js /usr/share/nginx/html/app.js
COPY src/style.css /usr/share/nginx/html/style.css
USER nginx
EXPOSE 8080
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
