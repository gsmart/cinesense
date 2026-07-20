FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json ./
COPY package-lock.json ./
COPY apps/web/package.json apps/web/package.json
RUN npm ci

FROM node:22-alpine AS builder
ARG NEXT_PUBLIC_CINESENSE_ENABLE_SHADOW_DIAGNOSTICS=false
ENV NEXT_PUBLIC_CINESENSE_ENABLE_SHADOW_DIAGNOSTICS=${NEXT_PUBLIC_CINESENSE_ENABLE_SHADOW_DIAGNOSTICS}
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm --workspace @cinesense/web run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/apps/web/.next/standalone ./
COPY --from=builder /app/apps/web/.next/static ./apps/web/.next/static
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
