import panda3d.core as p3d

import simplepbr
from simplepbr.envmap import (
    DEFAULT_PREFILTERED_SIZE,
    DEFAULT_PREFILTERED_SAMPLES,
)

def main(src, dst) -> None:

    envmap = simplepbr.EnvMap.from_file_path(
        src,
        prefiltered_size=DEFAULT_PREFILTERED_SIZE,
        prefiltered_samples=DEFAULT_PREFILTERED_SAMPLES,
        blocking_prepare=True,
    )

    envmap.write(dst)

if __name__ == '__main__':
    main("env.hdr", "envmap.env")