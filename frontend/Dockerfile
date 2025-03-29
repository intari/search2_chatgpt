# Используем официальный образ Nginx
FROM nginx:stable-alpine

# Удаляем стандартную конфигурацию Nginx
RUN rm /etc/nginx/conf.d/default.conf

# Копируем нашу конфигурацию (если она есть в папке frontend, иначе она берется из ./nginx)
# COPY nginx.conf /etc/nginx/conf.d/default.conf

# Копируем статичные файлы фронтенда
COPY index.html /usr/share/nginx/html/index.html

# Открываем порт 80
EXPOSE 80

# Команда для запуска Nginx
CMD ["nginx", "-g", "daemon off;"]
