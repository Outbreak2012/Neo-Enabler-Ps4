# Makefile for NEOENABLER GoldHEN Plugin (neoenabler_sdk.prx)
# Requires OpenOrbis PS4 Toolchain (OO_PS4_TOOLCHAIN) and GoldHEN_Plugins_SDK (GOLDHEN_SDK)

TOOLCHAIN   := $(OO_PS4_TOOLCHAIN)
GH_SDK      := $(GOLDHEN_SDK)
TARGET      := neoenabler_sdk.prx

CC          := clang
LD          := ld.lld

CFLAGS      := --target=x86_64-pc-freebsd12-elf -fPIC -funwind-tables -O2 -Wall \
               -I"$(TOOLCHAIN)/include" -I"$(GH_SDK)/include"

LDFLAGS     := -m elf_x86_64 -pie --script "$(TOOLCHAIN)/link.x" --eh-frame-hdr \
               -L"$(TOOLCHAIN)/lib" -L"$(GH_SDK)" -lGoldHEN_Hook -lkernel

SRCS        := neoenabler_sdk.c
OBJS        := $(SRCS:.c=.o)

all: $(TARGET)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

$(TARGET): $(OBJS)
	$(LD) $(OBJS) -o $(TARGET).elf $(LDFLAGS)
	$(TOOLCHAIN)/bin/linux/create-fself -in=$(TARGET).elf -out=$(TARGET).oelf --lib=$(TARGET) --paid 0x3800000000000011

clean:
	rm -f $(OBJS) $(TARGET).elf $(TARGET).oelf $(TARGET)
