FROM node:22-alpine AS base
WORKDIR /app
COPY package.json package-lock.json ./
ARG NPM_CONFIG_STRICT_SSL=true
ENV NPM_CONFIG_STRICT_SSL=$NPM_CONFIG_STRICT_SSL
RUN npm ci

FROM base AS development
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]

FROM base AS production
COPY . .
ENV API_URL=http://backend:8000
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
