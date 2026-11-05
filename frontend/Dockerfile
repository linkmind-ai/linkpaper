FROM node:24-alpine

WORKDIR /app

RUN npm install -g pnpm@11

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

EXPOSE 5173

# 로컬 개발용 Vite 서버다. /api 요청은 VITE_BACKEND_ORIGIN으로 전달한다.
CMD ["pnpm", "dev", "--host", "0.0.0.0"]
