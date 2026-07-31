/** @type {import('next').NextConfig} */
const nextConfig = {
  assetPrefix: process.env.ENABLE_FE_PROXY === "true" ? "/fe-static" : undefined,
};

module.exports = nextConfig;
