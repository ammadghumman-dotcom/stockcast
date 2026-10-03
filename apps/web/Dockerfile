FROM node:22-alpine
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* ./
COPY apps/web/package.json apps/web/
COPY packages/shared/package.json packages/shared/
RUN pnpm install --frozen-lockfile || pnpm install
COPY . .
WORKDIR /repo/apps/web
EXPOSE 3000
CMD ["pnpm", "dev"]
