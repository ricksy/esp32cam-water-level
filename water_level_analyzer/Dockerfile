ARG BUILD_FROM
FROM ${BUILD_FROM}

# The analyzer package lives in ../analyzer; the add-on build context is this
# folder only, so install it from the release tag matching config.yaml.
ARG BUILD_VERSION=0.1.0
RUN pip install --no-cache-dir \
    "water-level[service] @ https://github.com/ricksy/esp32cam-water-level/archive/refs/tags/v${BUILD_VERSION}.tar.gz#subdirectory=analyzer"

CMD ["python", "-m", "water_level", "serve", "--options", "/data/options.json"]
