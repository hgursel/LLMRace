FROM node:20-alpine AS build
WORKDIR /ui
COPY package.json tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm install && npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /ui/dist /usr/share/nginx/html
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
