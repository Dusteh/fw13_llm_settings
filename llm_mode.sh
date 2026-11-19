#!/bin/sh

sudo modprobe ryzen_smu
sudo $HOME/bin/ryzenadj --apu-skin-temp=43 --stapm-limit=22000 --fast-limit=22000 --slow-limit=22000
