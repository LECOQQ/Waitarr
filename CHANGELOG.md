# Changelog

## [0.3.1](https://github.com/LECOQQ/Waitarr/compare/v0.3.0...v0.3.1) (2026-11-28)


### Documentation

* **architecture:** draw the hexagon and the state machine in Mermaid ([6c91e3a](https://github.com/LECOQQ/Waitarr/commit/6c91e3a8b4a2e598764e335a6929174511e20c51))

## [0.3.0](https://github.com/LECOQQ/Waitarr/compare/v0.2.0...v0.3.0) (2026-11-27)


### Features

* **http:** show the phase of each target and task in /healthz ([1157153](https://github.com/LECOQQ/Waitarr/commit/115715369938c79eb9ac4466fbca050b6fc08107))


### Bug Fixes

* **cli:** accept only http and https in status --url ([f9b81a0](https://github.com/LECOQQ/Waitarr/commit/f9b81a0fa5eb6a76c41a6d985c1582fe43efd342))
* **cli:** assess each service by its configured type in check ([cd15e68](https://github.com/LECOQQ/Waitarr/commit/cd15e688145c55c06390ad24b9f4f2361697d03a))
* **cli:** fail check when a service version cannot be read ([c58968f](https://github.com/LECOQQ/Waitarr/commit/c58968f9bc4fb2801983acbd614d6c6c79bc2b9f))
* **cli:** keep the https to plain http fallback warning visible ([6b65c83](https://github.com/LECOQQ/Waitarr/commit/6b65c83aa1d1a0f06910abf0976a80b76610b3ef))
* **compat:** call a version between tested ones by its name ([fa7f147](https://github.com/LECOQQ/Waitarr/commit/fa7f1474bc1d1c679373022ca14618f846424361))
* **config:** give each setting one contract and refuse empty values ([87cecb0](https://github.com/LECOQQ/Waitarr/commit/87cecb0bd0ef92069adbec8d1e0c2f142398504e))
* **config:** refuse a name or URL with a trailing newline ([6e36ce9](https://github.com/LECOQQ/Waitarr/commit/6e36ce967c024218758375268503b6e58322bcce))
* **docker:** upgrade the OS packages of the runtime image ([5260d5f](https://github.com/LECOQQ/Waitarr/commit/5260d5f3c8a03450074dcd53bbf9192e497aa14d))
* **engine:** clear pending_from with pending once a write is confirmed ([fcd0ba3](https://github.com/LECOQQ/Waitarr/commit/fcd0ba3046cfabbb3fdb247110397fb5e4a0be13))
* **engine:** count read and write failures of a target apart ([5aa99c0](https://github.com/LECOQQ/Waitarr/commit/5aa99c088a378c45a7312f259711d8d3c7942365))
* **engine:** name the phases in status and heartbeat, one ownership test ([7630a19](https://github.com/LECOQQ/Waitarr/commit/7630a19a10dd42c6f9b006cee4f3b7ff34f450bc))
* **engine:** put the observe marker after the name, share the reason ([7252455](https://github.com/LECOQQ/Waitarr/commit/7252455c6033f6c6d5ee4866aa20d81679f688a8))
* **engine:** skip the state write when a tick changed nothing ([d404076](https://github.com/LECOQQ/Waitarr/commit/d4040767fce0551cdf2c24a4d0b0aa781f850a4f))
* **http:** keep the versions off /healthz for a caller without the token ([5654301](https://github.com/LECOQQ/Waitarr/commit/5654301fa1119030fc3ea90886dea619fe1ee095))
* **http:** mark /healthz when the library folders are unreadable ([3ad2e5c](https://github.com/LECOQQ/Waitarr/commit/3ad2e5c11eadf3bb02e436753c5f079e89999aa0))
* **http:** report degraded when the first tick never comes ([4480e6d](https://github.com/LECOQQ/Waitarr/commit/4480e6d16e02a7a410a73b726d1c4b98a2403159))
* **http:** serve who watches what only to the token holder ([a5836e2](https://github.com/LECOQQ/Waitarr/commit/a5836e2818987000ceb37bac18663b312af8c4c4))
* **jellyfin:** warn once when the library folders cannot be read ([41342d9](https://github.com/LECOQQ/Waitarr/commit/41342d96eae6eaa2a6c678e62285bef72abdb26b))
* **policy:** clamp an activity memory from the future to now ([a304d0d](https://github.com/LECOQQ/Waitarr/commit/a304d0da94a6724bbe6c8ae9ae25785d087a749c))
* **records:** refuse a last_activity_at without a UTC offset ([7c86040](https://github.com/LECOQQ/Waitarr/commit/7c8604040ce62a424ef9f6f9ced3cb3f577c77f1))
* **records:** refuse the target shapes the machine never writes ([be25ef6](https://github.com/LECOQQ/Waitarr/commit/be25ef692f89c13a54dda83fe35fbf66866e86b8))
* **sast:** fetch the opengrep v2 binary under its new name ([08c7c88](https://github.com/LECOQQ/Waitarr/commit/08c7c888301678b70fb43338a72835d3a3574543))
* **scripts:** refuse Codex as a co-author from one list of agent names ([a5dcd8c](https://github.com/LECOQQ/Waitarr/commit/a5dcd8c1ad65dfae36b87bbaa42226433ed43a11))


### Performance Improvements

* **cli:** keep the adapters out of the health probe ([43b950b](https://github.com/LECOQQ/Waitarr/commit/43b950bfcaf84fc79732f311a25382c42ebce675))
* **http:** wake the server thread once a second and on stop ([2f1271c](https://github.com/LECOQQ/Waitarr/commit/2f1271cedab22028ec92f349e9a3a7ed0e23b494))


### Documentation

* **adr:** accept ADR 0016 and keep its figures without the story ([d10870d](https://github.com/LECOQQ/Waitarr/commit/d10870dbef47085927101392769766fc58715c83))
* **adr:** describe image distribution without a real deployment ([f870630](https://github.com/LECOQQ/Waitarr/commit/f870630f4c58d755063c888af2782929a8149652))
* **adr:** drop references to unpublished files ([f079ee1](https://github.com/LECOQQ/Waitarr/commit/f079ee152b7578dfcb2e7af5b43b654073bbde11))
* **adr:** drop the template labels from ADR 0009 ([24891dd](https://github.com/LECOQQ/Waitarr/commit/24891dd611d6ae4748d61d3a82f94e1f780c21d2))
* **adr:** point ADR 0013 at the code for the recovery cases ([fdba992](https://github.com/LECOQQ/Waitarr/commit/fdba992daa41951afd084af5b56c02cf0b59c8f4))
* **adr:** say pull requests build amd64 only ([8052fb4](https://github.com/LECOQQ/Waitarr/commit/8052fb4e6cd85d03218af8c56bba31af57881a98))
* **adr:** state the current design, not how it came to be ([4e7e569](https://github.com/LECOQQ/Waitarr/commit/4e7e569c495dd639024212e272f1635eb45bf6fa))
* **architecture:** list banner.py in the module map ([e069bbf](https://github.com/LECOQQ/Waitarr/commit/e069bbf92976f7de33a78e001cf1e3b1ae7b7d3f))
* **config:** attribute each healthz phase to what shows it ([1a0b759](https://github.com/LECOQQ/Waitarr/commit/1a0b759e9d4225f5d63102db442298c59a2725cb))
* **config:** count refused writes toward the failure threshold ([4823661](https://github.com/LECOQQ/Waitarr/commit/482366121b2743cc5a782bd4cd41841dfbce9f34))
* **config:** document name limits, healthz field and test scope ([c0f34ad](https://github.com/LECOQQ/Waitarr/commit/c0f34ad76a0ce398a78c7f6790cf18378bacb4fa))
* **config:** document the phase /healthz shows per target and task ([246ffb0](https://github.com/LECOQQ/Waitarr/commit/246ffb00d161a7d006c9c39cce170144e6399909))
* **config:** say check fails on an unreadable service version ([e394b94](https://github.com/LECOQQ/Waitarr/commit/e394b94836f40670e072a81bfacfa9782a7d2a75))
* link the task facts and the yielding rule to ADR 0013 ([a56d2af](https://github.com/LECOQQ/Waitarr/commit/a56d2af4da80c79d3cecab11277293d0374eda85))
* name the project template generically in the harness ADR ([712d559](https://github.com/LECOQQ/Waitarr/commit/712d559e211c8fe46ec654f95ebbe9cf89022be5))
* **notify:** list the source key of the webhook body ([75d03a8](https://github.com/LECOQQ/Waitarr/commit/75d03a83aef8f629387b8edb630c824dc999b5ce))
* **readme:** say which contention Waitarr protects against ([2a1734a](https://github.com/LECOQQ/Waitarr/commit/2a1734a0ca4fade314c7778f8d3938431c2aa291))
* **reconcile:** drop a state count the enum already gives ([55b1efd](https://github.com/LECOQQ/Waitarr/commit/55b1efd42aa14fd83f5933a65dec245112dacc0b))
* say what v1 and v2 mean, and stop using them ([5e20e17](https://github.com/LECOQQ/Waitarr/commit/5e20e179ff9849ff71ef37d7a46a4bfcaf95eb91))
* state the write order in the port and align ADR 0002 ([ea95e7a](https://github.com/LECOQQ/Waitarr/commit/ea95e7a4852f58f7a6adb285e23a7771c7436baf))

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
