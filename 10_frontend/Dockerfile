# Build from the repository root so conf/settings.yaml is in the build context:
#   docker build -t uns/frontend:local -f ./10_frontend/Dockerfile .

FROM node:22-alpine AS build
WORKDIR /app
COPY 10_frontend/package.json 10_frontend/package-lock.json 10_frontend/.npmrc ./
RUN npm ci
COPY 10_frontend/index.html 10_frontend/vite.config.ts 10_frontend/tsconfig.json 10_frontend/nginx.conf ./
COPY 10_frontend/src ./src
COPY 10_frontend/platform ./platform
COPY 10_frontend/public ./public
COPY conf/settings.yaml ./conf/settings.yaml
ARG VITE_GRAPHQL_URL=http://localhost:8000/graphql
ENV VITE_GRAPHQL_URL=$VITE_GRAPHQL_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY 10_frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
