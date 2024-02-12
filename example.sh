# standardising the image

skopeo copy docker://gcr.io/datadoghq/dd-lib-python-init:latest oci:py-init:latest
umoci raw unpack --rootless --image py-init py-init-rootfs

umoci init --layout py-init-standardised
umoci new --image py-init-standardised:latest
umoci insert --image py-init-standardised:latest --rootless --tag datadog-lib --opaque py-init-rootfs/datadog-init/ /datadog-lib

## optional: check rootfs
# umoci raw unpack --rootless --image py-init-standardised:datadog-lib tmp_rootfs

## optional: copy the image into the registry
# skopeo copy oci:py-init-standardised:datadog-lib docker://registry.ddbuild.io/apm-reliability-env/handmade/py-init-standardised:latest
## optional: copy the image into the local docker daemon
# skopeo copy oci:py-init-standardised:datadog-lib docker-daemon:registry.ddbuild.io/apm-reliability-env/handmade/py-init-standardised:latest

# actually installing the tracer

skopeo copy docker://registry.ddbuild.io/apm-reliability-env/handmade/py-init-standardised:latest oci:py-init-standardised:latest
umoci raw unpack --rootless --image py-init-standardised:latest py-init-standardised-rootfs

skopeo copy docker://registry.ddbuild.io/apm-reliability-env/handmade/real-django:latest oci:real-django:latest
umoci insert --image real-django:latest --rootless --tag datadog-lib --opaque py-init-standardised-rootfs/datadog-lib/ /datadog-lib

umoci config --image real-django:datadog-lib --tag traced --config.env PYTHONPATH=/datadog-lib/
skopeo copy oci:real-django:traced docker-daemon:real-django:traced