CC      ?= cc
CFLAGS  ?= -DTINY -std=c99 -Os -Wall -Wextra \
           -fno-stack-protector \
           -fno-asynchronous-unwind-tables \
           -fno-unwind-tables \
           -fno-builtin -ffreestanding \
           -ffunction-sections -fdata-sections
LDFLAGS ?= -nostdlib -nostartfiles -static \
           -Wl,--gc-sections -Wl,--build-id=none -Wl,-z,noseparate-code \
           -Wl,-z,common-page-size=512 -s

all: office office2 office3 office4 office5 office6

office: office.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office: $$(stat -c %s $@) bytes"

office2: office2.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office2: $$(stat -c %s $@) bytes"

office3: office3.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office3: $$(stat -c %s $@) bytes"

office4: office4.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office4: $$(stat -c %s $@) bytes"

office5: office5.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office5: $$(stat -c %s $@) bytes"

office6: office6.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office6: $$(stat -c %s $@) bytes"

clean:
	rm -f office office2 office3 office4 office5 office6 outbox.txt canvas.txt

.PHONY: clean
