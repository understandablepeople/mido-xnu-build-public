union iovecs {
    unsigned long long address;
    unsigned long long length;
};

#define uio_stackbuf_t _Alignas(union iovecs) char

extern void consume(void *buffer, unsigned long size);

void fixed_buffer(void);
void dynamic_buffer(unsigned long size);

void fixed_buffer(void)
{
    uio_stackbuf_t buffer[137];
    _Static_assert(sizeof(buffer) == 137, "byte count preserved");
    _Static_assert(__alignof__(buffer) == _Alignof(union iovecs), "array alignment preserved");
    consume(buffer, sizeof(buffer));
}

void dynamic_buffer(unsigned long size)
{
    uio_stackbuf_t buffer[size];
    consume(buffer, sizeof(buffer));
}
