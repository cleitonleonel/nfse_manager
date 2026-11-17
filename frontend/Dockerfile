FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html favicon.ico favicon.svg /usr/share/nginx/html/
COPY css /usr/share/nginx/html/css
COPY js /usr/share/nginx/html/js
COPY views /usr/share/nginx/html/views

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
