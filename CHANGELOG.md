# Changelog

## 0.1.0 (2026-10-28)


### Features

* **compose:** switch mode, log level and poll interval from .env ([36615bc](https://github.com/LECOQQ/Waitarr/commit/36615bc1d1a444200444e9f6616b053b3e4fbc34))
* **config:** define Jellyfin and qBittorrent entirely from the environment ([f56192e](https://github.com/LECOQQ/Waitarr/commit/f56192e98a1ec857b9d1a2b85a5ce75cb41372e9))
* **config:** throttle by default; observation is one setting away ([6b3e4a8](https://github.com/LECOQQ/Waitarr/commit/6b3e4a8b7b64787f7552f494b25eb2c9c4494a41))
* **core:** log every session change and why a target is released ([06c2317](https://github.com/LECOQQ/Waitarr/commit/06c231794ac83bdc904e0b35daf255afc654dbf2))
* **core:** throttle targets during playback and give back only what Waitarr took ([31c2c8e](https://github.com/LECOQQ/Waitarr/commit/31c2c8e744d413509c3051a628c31852d86ff1a8))
* **policy:** filter playbacks by Jellyfin library ([98a0f6d](https://github.com/LECOQQ/Waitarr/commit/98a0f6d7ba8a6047ec7a53095c13deb47264939d))
* **qbittorrent:** warn when µTP or LAN traffic escapes the throttle ([429ff15](https://github.com/LECOQQ/Waitarr/commit/429ff15e6853b51cfdd9888884bc12a4c55a5015))
* watch Jellyfin and throttle qBittorrent through its alternative limits ([6fa0533](https://github.com/LECOQQ/Waitarr/commit/6fa0533fdc57ee8b40d3bf0a7f3616a543661a07))


### Bug Fixes

* close the gaps an independent review found in ownership and secrets ([35e6af3](https://github.com/LECOQQ/Waitarr/commit/35e6af3baaf07fd5e96f92c51376976efcf28f87))
* **config:** treat an empty environment variable as absent ([eba588c](https://github.com/LECOQQ/Waitarr/commit/eba588c5e58e65ed7edf4b482bd471a96d924fe2))
* **deps:** depend on qbit-ops 0.7 from PyPI instead of a Git revision ([5ff3635](https://github.com/LECOQQ/Waitarr/commit/5ff36357ff687830e044245878f68ffa9bb3121f))
* **logging:** log an unreachable service once instead of every tick ([f15dd09](https://github.com/LECOQQ/Waitarr/commit/f15dd09d1fad37274b8b45de02a9958482c6003b))


### Documentation

* add a pull request template and issue forms ([9f84dab](https://github.com/LECOQQ/Waitarr/commit/9f84dab9cf127f7d3c300312bfe877519345771f))
* **adr:** word the decisions impersonally ([335985b](https://github.com/LECOQQ/Waitarr/commit/335985bcef46168335589e9178d4938d1af037cf))
* **assets:** add the logo and the social preview ([81eb819](https://github.com/LECOQQ/Waitarr/commit/81eb8190fbbb829f3328f45cddd175c67ab2577b))
* **assets:** drop the pills row from the social preview ([aa5bfdf](https://github.com/LECOQQ/Waitarr/commit/aa5bfdfb855b0232f7193e0cadac051c4805c711))
* **assets:** render the social preview in anthracite with Lato ([7c94a17](https://github.com/LECOQQ/Waitarr/commit/7c94a1779250b071f01c9791e9193593e6855364))
* **assets:** switch to the retro cartoon logo ([6ea18d5](https://github.com/LECOQQ/Waitarr/commit/6ea18d51da478d17244546ace7f73c2b716366a3))
* explain Waitarr, its decisions and how to verify it ([35a2f03](https://github.com/LECOQQ/Waitarr/commit/35a2f031c349939e039717eb501bd492cbddb4a0))
* list what leaves the repository before it goes public ([dff51ff](https://github.com/LECOQQ/Waitarr/commit/dff51ff01598aae5f90441e2462f7b29688ccbbb))
* **readme:** lead with the tagline, who it is for and why it never pauses ([8272d1e](https://github.com/LECOQQ/Waitarr/commit/8272d1ee906777d9069036f1e87264de8d973f80))
* **readme:** leave the mode to its active default ([80f9773](https://github.com/LECOQQ/Waitarr/commit/80f9773fd222ee4313723a85a99b2482f58ab91a))
* **readme:** make Compose the one way in, with a self-contained block ([edb64fe](https://github.com/LECOQQ/Waitarr/commit/edb64feac4db98bc941ca8892e25b22d746e9720))
* **readme:** pass the Compose secrets by reference ([f075ab6](https://github.com/LECOQQ/Waitarr/commit/f075ab6b3f0b4d24b3b8dedaa9b0b6b89b15ff32))
