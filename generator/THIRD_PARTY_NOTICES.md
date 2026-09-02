# Third-party notices

The `generator/` source code written for DeepTelecom is distributed under the repository's [Apache License 2.0](../LICENSE). No third-party Python source, binary package, mesh, generated dataset, or scene asset is copied into this directory.

Running the generator installs or imports third-party projects, including:

- [Sionna](https://github.com/NVlabs/sionna) and [Sionna RT](https://nvlabs.github.io/sionna/rt/), including the built-in Étoile scene;
- [TensorFlow](https://github.com/tensorflow/tensorflow);
- [Mitsuba 3](https://github.com/mitsuba-renderer/mitsuba3) and [Dr.Jit](https://github.com/mitsuba-renderer/drjit), normally installed as transitive Sionna RT dependencies;
- [NumPy](https://github.com/numpy/numpy), [SciPy](https://github.com/scipy/scipy), [Matplotlib](https://github.com/matplotlib/matplotlib), and [Pillow](https://github.com/python-pillow/Pillow).

Those projects and their assets are governed by their respective licenses and notices, not by the DeepTelecom license. Before redistribution, inspect the license metadata of the exact installed versions and retain all notices required by the upstream projects. The pinned package versions in `requirements.txt` describe the tested environment; they do not alter upstream license terms.

