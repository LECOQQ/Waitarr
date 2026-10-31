# Changelog

## [0.2.0](https://github.com/LECOQQ/Waitarr/compare/v0.1.1...v0.2.0) (2026-10-31)


### Features

* **config:** suspend_tasks and tasks per Jellyfin source ([d10c603](https://github.com/LECOQQ/Waitarr/commit/d10c60305db4a968afa107e8bc7f9a41aa1b0a53))
* **core:** add the pure task ownership machine ([ce48d1a](https://github.com/LECOQQ/Waitarr/commit/ce48d1a95e4b65b61014a8c86f1cda570bf69e1d))
* **core:** model scheduled tasks and the TaskHost port ([1d5d2fa](https://github.com/LECOQQ/Waitarr/commit/1d5d2fa5d243d8e8e50538ae0d80334720aab2fd))
* **core:** read and write state schema 2 with a tasks section ([ac5244e](https://github.com/LECOQQ/Waitarr/commit/ac5244e910747595d4fba83186d89b1aafd7ea13))
* **engine:** suspend listed tasks during the hold and restore them ([8b94319](https://github.com/LECOQQ/Waitarr/commit/8b9431943184800978b0f033503462a4bde15c84))
* **jellyfin:** read, stop and start scheduled tasks ([74b54fa](https://github.com/LECOQQ/Waitarr/commit/74b54fa6a74a67a9b972de67d7b91bc51a3c130e))
* **service:** log one startup block with the configuration and versions ([8d4a9fc](https://github.com/LECOQQ/Waitarr/commit/8d4a9fc9e3e50b8ba8080ac6a495881c59cde498))
* **service:** name the version when the start fails ([8efc5b0](https://github.com/LECOQQ/Waitarr/commit/8efc5b0b4a39c411c71d7e81985e768baf6dd467))
* **status:** show owned tasks in healthz, check and restore ([235cb88](https://github.com/LECOQQ/Waitarr/commit/235cb88ee3691d4e7a2b02b38914d10dbf56e947))


### Bug Fixes

* **engine:** clear the task error once any read of the tasks succeeds ([7ec6386](https://github.com/LECOQQ/Waitarr/commit/7ec6386038875a981751bab400d0b06343081551))
* **engine:** do not wait for a yielded task to finish cancelling ([1f8794d](https://github.com/LECOQQ/Waitarr/commit/1f8794d1dda6bac4f94c83a3207fbac75998004d))
* **engine:** mark the forget lines of a task with [observe] in observation ([4009113](https://github.com/LECOQQ/Waitarr/commit/400911330b4c928e2683facfc9705d005c0a1cc1))
* **service:** log a diagnostic when it appears or goes, not every hour ([0053c1d](https://github.com/LECOQQ/Waitarr/commit/0053c1d1e0760b8d9afe2b812d4e885b4a923eca))


### Documentation

* **adr:** recommend keeping downloads in progress off the media disk ([67a9331](https://github.com/LECOQQ/Waitarr/commit/67a93311ec81b03abf2c0ef237b76a0b593c6e6d))
* **adr:** record that pre-allocation costs nothing on NFS 4.2 ([be378a8](https://github.com/LECOQQ/Waitarr/commit/be378a89b03103fd353026ba63d720a64918d5a4))
* **adr:** record the crash and race resolution of 0013 ([95cc089](https://github.com/LECOQQ/Waitarr/commit/95cc0895fd4da65fd41b3aaa64de31bcdae20b58))
* **adr:** record why downloads are throttled like seeds ([98d00bb](https://github.com/LECOQQ/Waitarr/commit/98d00bb9f861082e6ac3ae28aa6bf2ac68ec3a8f))
* **adr:** record why no throttle is taken ahead of playback ([03c6bc7](https://github.com/LECOQQ/Waitarr/commit/03c6bc72da203a1652039273fa64fa4077bccd1c))
* document task suspension and ADR 0013 ([5787165](https://github.com/LECOQQ/Waitarr/commit/5787165cd88d9c492932f0b3c6bc471527f66720))
* word the release and merge rules impersonally ([95a1099](https://github.com/LECOQQ/Waitarr/commit/95a1099ac0dfc31ed0ddd8a1bfb124531b9f3ac2))

## [0.1.1](https://github.com/LECOQQ/Waitarr/compare/v0.1.0...v0.1.1) (2026-10-30)


### Bug Fixes

* **sast:** run the engine test from tests/unit without the conftest ([dcb4908](https://github.com/LECOQQ/Waitarr/commit/dcb490849a5337a3869bf24aac947aeeddd5e74c))


### Documentation

* **security:** add a security policy ([e53483d](https://github.com/LECOQQ/Waitarr/commit/e53483d2683871a9f46589a2e1171ac493ae52c5))

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
