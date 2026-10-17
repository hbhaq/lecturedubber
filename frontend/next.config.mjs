export default {
  distDir: process.env.STUDIO_BUILD_DIR || '.next',
  ...(process.env.STUDIO_STATIC_EXPORT === '1' ? {output:'export'} : {})
};
