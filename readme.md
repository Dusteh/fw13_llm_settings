### Framework 13" AMD Ryzen 7 7840U w/ Radeon 780M Graphics - LLM Configuration Repository

#### Purpose
This repository exists to store the documentation, scripts, findings, and processes to configure my Framework 13" AMD Ryzen 7 7840U for use with Ollama and OpenCode and was tested with Qwen3 30b-A3B and Qwen3.6 35b-a3b to achive a Tokens Per Second between 20 and 35 on Vulkan 

#### Disclaimer
> [!WARNING]
> **A user of this repository should be fully aware that this process has the potential to damage your device, or shorten component life.**
>
> **I provide this information for others to base their own exploration to configure their device and can take no liability for anything you do based off this information.**

This is what worked for my configuration so far and I will strive to keep this repo up to date with any additional findings.

This process used Anthropic Claude Opus 5.5 to research this process and write the performance monitoring python script.

#### Usage

This repository provides the information to adjust the wattage that your integrated GPU will consume without triggering the default safeguards of the Surface Skin Temperature sensor; this sensor samples the chassis heat so that users don't burn themselves while operating the device. 


#### Install

Tested on Ubuntu 26.04 with Secure Boot on. Clone this repository and run the install script as your normal user (it calls `sudo` where needed):

```sh
git clone <this repo> && cd fw13_llm_settings
./install.sh
```

The script installs the build tools, the [amkillam fork of `ryzen_smu`](https://github.com/amkillam/ryzen_smu) kernel module through DKMS, and builds [RyzenAdj](https://github.com/FlyGoat/RyzenAdj) into `~/bin/ryzenadj`. If Secure Boot is on and the DKMS signing key isn't enrolled yet, it asks for a one-time password. Reboot, choose "Enroll MOK", and run `./install.sh` again. You can run it again safely at any time.

Then, before each LLM session:

```sh
./llm_mode.sh
```

The cap resets on reboot and when the charger is unplugged, so run it again after either. See [framework13-llm-slowdown.md](framework13-llm-slowdown.md) for the full findings.

It is recommended that you also move `llm_mode.sh` to a bin directory or your PATH variable

#### Credits

- [FlyGoat/RyzenAdj](https://github.com/FlyGoat/RyzenAdj): the tool that reads and sets the APU's power and thermal limits.
- [amkillam/ryzen_smu](https://github.com/amkillam/ryzen_smu): the `ryzen_smu` fork with Phoenix support, which lets RyzenAdj work with Secure Boot on. It is based on [leogx9r's original `ryzen_smu`](https://gitlab.com/leogx9r/ryzen_smu).
- [AlxHnr](https://github.com/AlxHnr): [amd-ryzen-ignore-stapm](https://github.com/AlxHnr/amd-ryzen-ignore-stapm), for handling firmware limit resets.
- [Framework community forum](https://community.frame.work/t/radeon-780m-thermal-throttling-stays-on-until-i-reboot/58576): reports of the same STAPM throttling on the 7840U.
- [llama.cpp](https://github.com/ggml-org/llama.cpp) and [Ollama](https://github.com/ollama/ollama): the inference engine and runtime used for testing.
- [Vulkan](https://www.vulkan.org/): the GPU backend llama.cpp runs on here. It was chosen over ROCm, which was about 25% slower at generation on the 780M.
- [opencode](https://opencode.ai): the coding client.
- [Qwen](https://huggingface.co/Qwen): the models that were tested.
- [Anthropic Claude](https://www.anthropic.com/claude): research, writing, and `llm_perflog.py`.

All other references are under Sources in [framework13-llm-slowdown.md](framework13-llm-slowdown.md#sources).
