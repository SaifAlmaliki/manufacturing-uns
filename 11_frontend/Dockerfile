# Build from the repository root so conf/settings.yaml is in the build context:
#   docker build -t uns/frontend:local -f ./11_frontend/Dockerfile .

FROM node:22-alpine AS build
WORKDIR /app
COPY 11_frontend/package.json 11_frontend/package-lock.json 11_frontend/.npmrc ./
RUN npm ci
COPY 11_frontend/index.html 11_frontend/vite.config.ts 11_frontend/tsconfig.json 11_frontend/nginx.conf ./
COPY 11_frontend/src ./src
COPY 11_frontend/platform ./platform
COPY conf/settings.yaml ./conf/settings.yaml
ARG VITE_GRAPHQL_URL=http://localhost:8000/graphql
ENV VITE_GRAPHQL_URL=$VITE_GRAPHQL_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY 11_frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
