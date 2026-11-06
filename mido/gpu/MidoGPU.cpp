#include <pexpert/arm64/board_config.h>
/*
 * SweetGPU: user client for the Adreno 530 (bsd/dev/sweet_gpu.c, kernel API
 * in bsd/dev/sweet_gpu.h; GPU up with boot-arg sweetgpu=8).
 *
 * Selectors:
 *   0 map user memory   in: address, length[, flags: bit 0 read-only (quad
 *                       source only)]   out: GPU VA of address
 *   1 map IOSurface     in: surface id        out: GPU VA, allocation size
 *   2 unmap             in: GPU VA returned by 0 or 1
 *   3 quad              in: struct sweet_gpu_quad (both images inside this
 *                       client's mappings), runs synchronously
 * Mappings wire the memory (user pages / surface) until unmapped or the
 * client closes. For selectors 0-3 user space never supplies GPU commands
 * or physical addresses: the kernel builds the command stream and checks
 * every range.
 *
 * Buffer objects and command streams, for a user-space driver (Mesa
 * freedreno through tools/sweetgl's msm emulation):
 *   10 bo new           in: size              out: handle, GPU VA, address
 *                       (zeroed wired memory, cached in the caller,
 *                       uncached for the GPU)
 *   11 bo free          in: handle (waits for the last submit using it)
 *   12 bo import        in: IOSurface id      out: handle, GPU VA, size
 *                       (the surface's pages)
 *   13 submit           struct in: struct sweet_gpu_submit + ibs[nr_ibs] +
 *                       u32 handles[nr_bos] (every bo the IBs touch)
 *                       out: sequence number
 *   14 wait             in: sequence number, timeout ms (0: poll)
 *   15 info             out: chip id, GMEM size, GMEM base, max Hz, 0
 *   16 bo cpu prep      in: handle (after its last submit completed: drops
 *                       the CPU's cached lines, so the CPU sees GPU writes)
 * The CPU cache is cleaned and invalidated over every bo a submit lists.
 * The GPU executes these streams as they are, with access to every GPU VA
 * mapping (one address space): a client can read and write other clients'
 * GPU memory. Acceptable on this single-user bring-up device only.
 */
#if defined(MIDO)
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOKitKeys.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <pexpert/pexpert.h>
#include <IOKit/IOMemoryDescriptor.h>
#include "MidoSurface.h"
#include <sys/errno.h>
#include "mido_gpu_backend.h"

extern "C" void proc_selfname(char *buf, int size);

#define SWEET_GPU_MAX_MAPS      128
#define SWEET_GPU_MAX_MAP_BYTES (64ull << 20)
#define SWEET_GPU_MAX_BOS       16384u
#define SWEET_GPU_MAX_BO_BYTES  (256ull << 20)
#define SWEET_GPU_CLIENT_BYTES  (768ull << 20)     /* own buffers per client */

extern "C" void flush_dcache64(addr64_t addr, unsigned count, int phys);
extern "C" boolean_t pmap_is_modified(ppnum_t pn);
extern "C" void pmap_clear_modify(ppnum_t pn);
extern "C" boolean_t pmap_valid_page(ppnum_t pn);

/*
 * Push out the CPU's writes to page pa if any landed since the last call:
 * the pmap's modified bit is set by the first user write after
 * pmap_clear_modify (write-protect + fast fault). Cleared before the flush,
 * so a write racing with it is caught next time. Kernel (physmap) writes do
 * not set it: bos are flushed whole when created or imported.
 * ponytail: also tells the VM the page is clean; fine while bos are wired.
 */
static void
flush_if_written(uint64_t pa)
{
	ppnum_t pn = (ppnum_t)(pa >> PAGE_SHIFT);
	if (!pmap_valid_page(pn)) {             /* not managed: no modified bit, always */
		flush_dcache64((addr64_t)pa, PAGE_SIZE, TRUE);
	} else if (pmap_is_modified(pn)) {
		pmap_clear_modify(pn);
		flush_dcache64((addr64_t)pa, PAGE_SIZE, TRUE);
	}
}

struct sweet_gpu_submit {
	uint32_t nr_ibs, nr_bos;
};

static IOBufferMemoryDescriptor *gFencePage;

class SweetGPU : public IOService {
	OSDeclareDefaultStructors(SweetGPU);

public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(SweetGPU, IOService);

bool
SweetGPU::start(IOService *provider)
{
	unsigned mode = 0;
	if (!PE_parse_boot_argn("midogpubridge", &mode, sizeof(mode)) || mode != 1) {
		return false;
	}
	if (!IOService::start(provider)) {
		return false;
	}
	gFencePage = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
	    kIODirectionInOut | kIOMemoryKernelUserShared, page_size, page_size);
	if (gFencePage != NULL) {
		IOByteCount seg = 0;
		uint64_t pa = gFencePage->getPhysicalSegment(0, &seg, kIOMemoryMapperNone);
		bzero(gFencePage->getBytesNoCopy(), page_size);
		flush_dcache64((addr64_t)pa, (unsigned)page_size, TRUE);
		sweet_gpu_set_fence_page((uintptr_t)gFencePage->getBytesNoCopy(), pa);
	}
	setProperty(kIOUserClientClassKey, "SweetGPUUserClient");
	registerService();
	IOLog("SWEET GPU: SweetGPU registered\n");
	return true;
}

struct sweet_gpu_map {
	uint64_t gva;                   /* GPU VA of the first page */
	uint64_t start, len;            /* GPU VA range the client may use */
	IOMemoryDescriptor *md;         /* prepared (wired) */
	MidoSurface *surface;          /* retained, for surface mappings */
};

struct sweet_gpu_bo {
	uint64_t iova, size;
	IOMemoryDescriptor *md;         /* own buffer or a surface's memory; wired */
	IOMemoryMap *umap;              /* own buffers: the client's mapping */
	MidoSurface *surface;          /* imports */
	uint64_t *pa;                   /* pages, for cache maintenance */
	uint32_t npages;
	uint32_t last_seq;              /* last submit listing it */
	bool used;                      /* listed in a submit at least once */
};

class SweetGPUUserClient : public IOUserClient {
	OSDeclareDefaultStructors(SweetGPUUserClient);

	task_t fTask;
	IOLock *fLock;
	struct sweet_gpu_map fMaps[SWEET_GPU_MAX_MAPS];
	struct sweet_gpu_bo *fBos;
	uint32_t fBoCap;
	uint64_t fBoBytes;

	IOReturn mapDescriptor(IOMemoryDescriptor *md, uint64_t offset, uint64_t len,
	    MidoSurface *surface, bool readonly, uint64_t *gvaOut);
	void unmapSlot(unsigned i);
	bool owns(uint64_t va, uint64_t len);
	struct sweet_gpu_bo *newBo(uint32_t *handle);
	struct sweet_gpu_bo *bo(uint64_t handle);
	void freeBo(struct sweet_gpu_bo *b);
	IOReturn boNew(uint64_t size, uint64_t *out);
	IOReturn boImport(uint32_t id, uint64_t *out);
	IOReturn submit(const void *in, size_t len, uint64_t *seq);

public:
	bool initWithTask(task_t owningTask, void *securityID, UInt32 type) APPLE_KEXT_OVERRIDE;
	void free() APPLE_KEXT_OVERRIDE;
	IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
	    IOExternalMethodDispatch *dispatch, OSObject *target, void *reference) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(SweetGPUUserClient, IOUserClient);

bool
SweetGPUUserClient::initWithTask(task_t owningTask, void *securityID, UInt32 type)
{
	if (!sweet_gpu_ready()) {
		return false;
	}
	if (!IOUserClient::initWithTask(owningTask, securityID, type)) {
		return false;
	}
	fTask = owningTask;
	bzero(fMaps, sizeof(fMaps));
	fLock = IOLockAlloc();
	char name[32];
	proc_selfname(name, sizeof(name));
	IOLog("SWEET GPU: user client opened by %s\n", name);
	return fLock != NULL;
}

void
SweetGPUUserClient::free()
{
	if (fLock != NULL) {
		for (unsigned i = 0; i < SWEET_GPU_MAX_MAPS; i++) {
			unmapSlot(i);
		}
		for (uint32_t i = 0; i < fBoCap; i++) {
			freeBo(&fBos[i]);
		}
		IOLockFree(fLock);
		fLock = NULL;
	}
	if (fBos != NULL) {
		IOFreeData(fBos, fBoCap * sizeof(fBos[0]));
		fBos = NULL;
	}
	IOUserClient::free();
}

IOReturn
SweetGPUUserClient::clientClose(void)
{
	IOLockLock(fLock);
	for (unsigned i = 0; i < SWEET_GPU_MAX_MAPS; i++) {
		unmapSlot(i);
	}
	for (uint32_t i = 0; i < fBoCap; i++) {
		freeBo(&fBos[i]);
	}
	IOLockUnlock(fLock);
	terminate();
	return kIOReturnSuccess;
}

/* Lock held (or the client is being freed). */
void
SweetGPUUserClient::unmapSlot(unsigned i)
{
	struct sweet_gpu_map *m = &fMaps[i];
	if (m->md == NULL) {
		return;
	}
	sweet_gpu_vm_unmap(m->gva);
	m->md->complete();
	m->md->release();
	OSSafeReleaseNULL(m->surface);
	bzero(m, sizeof(*m));
}

/* Lock held. */
bool
SweetGPUUserClient::owns(uint64_t va, uint64_t len)
{
	for (unsigned i = 0; i < SWEET_GPU_MAX_MAPS; i++) {
		const struct sweet_gpu_map *m = &fMaps[i];
		if (m->md != NULL && va >= m->start && len <= m->len && va - m->start <= m->len - len) {
			return true;
		}
	}
	return false;
}

/*
 * Lock held. Wire md (takes over the caller's reference on success), map
 * its pages, record [gva + offset, + len) as usable.
 */
IOReturn
SweetGPUUserClient::mapDescriptor(IOMemoryDescriptor *md, uint64_t offset, uint64_t len,
    MidoSurface *surface, bool readonly, uint64_t *gvaOut)
{
	unsigned slot = SWEET_GPU_MAX_MAPS;
	for (unsigned i = 0; i < SWEET_GPU_MAX_MAPS && slot == SWEET_GPU_MAX_MAPS; i++) {
		if (fMaps[i].md == NULL) {
			slot = i;
		}
	}
	uint64_t size = md->getLength();
	if (slot == SWEET_GPU_MAX_MAPS || size == 0 || size > SWEET_GPU_MAX_MAP_BYTES || (size & PAGE_MASK)) {
		return kIOReturnNoResources;
	}
	if (md->prepare(readonly ? kIODirectionOut : kIODirectionInOut) != kIOReturnSuccess) {
		return kIOReturnVMError;
	}
	uint32_t npages = (uint32_t)(size / PAGE_SIZE);
	uint64_t *pa = (uint64_t *)IOMallocData(npages * sizeof(uint64_t));
	bool ok = pa != NULL;
	for (uint32_t p = 0; ok && p < npages; p++) {
		IOByteCount seg = 0;
		pa[p] = md->getPhysicalSegment((IOByteCount)p * PAGE_SIZE, &seg, kIOMemoryMapperNone);
		ok = pa[p] != 0 && (pa[p] & PAGE_MASK) == 0 && seg >= PAGE_SIZE;
	}
	uint64_t gva = ok ? sweet_gpu_vm_map(pa, npages, readonly) : 0;
	if (pa != NULL) {
		IOFreeData(pa, npages * sizeof(uint64_t));
	}
	if (gva == 0) {
		md->complete();
		return kIOReturnNoMemory;
	}
	fMaps[slot].gva = gva;
	fMaps[slot].start = gva + offset;
	fMaps[slot].len = len;
	fMaps[slot].md = md;
	fMaps[slot].surface = surface;
	*gvaOut = gva + offset;
	return kIOReturnSuccess;
}

/* Lock held: a free slot (the table grows by doubling), or NULL. */
struct sweet_gpu_bo *
SweetGPUUserClient::newBo(uint32_t *handle)
{
	for (uint32_t i = 0; i < fBoCap; i++) {
		if (fBos[i].md == NULL) {
			*handle = i + 1;
			return &fBos[i];
		}
	}
	uint32_t cap = fBoCap ? fBoCap * 2 : 256;
	if (cap > SWEET_GPU_MAX_BOS) {
		return NULL;
	}
	struct sweet_gpu_bo *n = (struct sweet_gpu_bo *)IOMallocZeroData(cap * sizeof(n[0]));
	if (n == NULL) {
		return NULL;
	}
	if (fBos != NULL) {
		memcpy(n, fBos, fBoCap * sizeof(n[0]));
		IOFreeData(fBos, fBoCap * sizeof(fBos[0]));
	}
	fBos = n;
	*handle = fBoCap + 1;
	fBoCap = cap;
	return &fBos[*handle - 1];
}

/* Lock held: the bo for a handle, or NULL. */
struct sweet_gpu_bo *
SweetGPUUserClient::bo(uint64_t handle)
{
	return handle >= 1 && handle <= fBoCap && fBos[handle - 1].md != NULL ? &fBos[handle - 1] : NULL;
}

/*
 * Lock held (or the client is being freed). The GPU may still use the
 * memory: wait for the last submit that listed the bo first (a hung GPU
 * fails the wait at once; its memory is then left mapped and wired rather
 * than freed under a GPU that might wake up).
 */
void
SweetGPUUserClient::freeBo(struct sweet_gpu_bo *b)
{
	if (b->md == NULL) {
		return;
	}
	if (b->used && sweet_gpu_wait(b->last_seq, 2000) != 0) {
		printf("SWEET GPU: bo %llx busy at free, leaked\n", b->iova);
		bzero(b, sizeof(*b));
		return;
	}
	sweet_gpu_vm_unmap(b->iova);
	OSSafeReleaseNULL(b->umap);
	IOFreeData(b->pa, b->npages * sizeof(uint64_t));
	if (b->surface != NULL) {
		b->md->complete();
		b->surface->release();
	} else {
		fBoBytes -= b->size;
	}
	b->md->release();
	bzero(b, sizeof(*b));
}

/* out: handle, GPU VA, user address. */
IOReturn
SweetGPUUserClient::boNew(uint64_t size, uint64_t *out)
{
	size = round_page_64(size);
	if (size == 0 || size > SWEET_GPU_MAX_BO_BYTES || fBoBytes + size > SWEET_GPU_CLIENT_BYTES) {
		return kIOReturnNoMemory;
	}
	uint32_t handle;
	struct sweet_gpu_bo *b = newBo(&handle);
	if (b == NULL) {
		return kIOReturnNoResources;
	}
	IOBufferMemoryDescriptor *md = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
	    kIODirectionInOut | kIOMemoryKernelUserShared, size, page_size);
	if (md == NULL) {
		return kIOReturnNoMemory;
	}
	uint32_t npages = (uint32_t)(size / PAGE_SIZE);
	uint64_t *pa = (uint64_t *)IOMallocData(npages * sizeof(uint64_t));
	bool ok = pa != NULL;
	for (uint32_t p = 0; ok && p < npages; p++) {
		IOByteCount seg = 0;
		pa[p] = md->getPhysicalSegment((IOByteCount)p * PAGE_SIZE, &seg, kIOMemoryMapperNone);
		ok = pa[p] != 0 && (pa[p] & PAGE_MASK) == 0 && seg >= PAGE_SIZE;
		if (ok) {
			/* zeroed through the cached kernel alias: push it out, drop the lines */
			flush_dcache64((addr64_t)pa[p], PAGE_SIZE, TRUE);
		}
	}
	uint64_t gva = ok ? sweet_gpu_vm_map(pa, npages, false) : 0;
	/*
	 * Cached in the caller like everywhere else: a write-combined user
	 * mapping of managed pages makes the pmap rewrite their physmap PTEs
	 * (froze boot 0150a). Cache maintenance at submit and cpu prep instead.
	 */
	IOMemoryMap *umap = gva ? md->createMappingInTask(fTask, 0, kIOMapAnywhere) : NULL;
	if (umap == NULL) {
		if (gva) {
			sweet_gpu_vm_unmap(gva);
		}
		if (pa != NULL) {
			IOFreeData(pa, npages * sizeof(uint64_t));
		}
		md->release();
		return kIOReturnNoMemory;
	}
	*b = (struct sweet_gpu_bo){ .iova = gva, .size = size, .md = md, .umap = umap, .pa = pa, .npages = npages };
	fBoBytes += size;
	out[0] = handle;
	out[1] = gva;
	out[2] = umap->getAddress();
	return kIOReturnSuccess;
}

/* out: handle, GPU VA, size. */
IOReturn
SweetGPUUserClient::boImport(uint32_t id, uint64_t *out)
{
	MidoSurface *s = mido_surface_copy(id);
	if (s == NULL || s->memory == NULL) {
		OSSafeReleaseNULL(s);
		return kIOReturnNotFound;
	}
	IOMemoryDescriptor *md = s->memory;
	uint64_t size = md->getLength();
	uint32_t handle;
	struct sweet_gpu_bo *b = (size && !(size & PAGE_MASK) && size <= SWEET_GPU_MAX_BO_BYTES) ? newBo(&handle) : NULL;
	if (b == NULL || md->prepare() != kIOReturnSuccess) {
		s->release();
		return b == NULL ? kIOReturnNoResources : kIOReturnVMError;
	}
	uint32_t npages = (uint32_t)(size / PAGE_SIZE);
	uint64_t *pa = (uint64_t *)IOMallocData(npages * sizeof(uint64_t));
	bool ok = pa != NULL;
	for (uint32_t p = 0; ok && p < npages; p++) {
		IOByteCount seg = 0;
		pa[p] = md->getPhysicalSegment((IOByteCount)p * PAGE_SIZE, &seg, kIOMemoryMapperNone);
		ok = pa[p] != 0 && (pa[p] & PAGE_MASK) == 0 && seg >= PAGE_SIZE;
		if (ok) {
			/* lines left by the zero-fill or earlier CPU use; submits flush only written pages */
			if (pmap_valid_page((ppnum_t)(pa[p] >> PAGE_SHIFT))) {
				pmap_clear_modify((ppnum_t)(pa[p] >> PAGE_SHIFT));
			}
			flush_dcache64((addr64_t)pa[p], PAGE_SIZE, TRUE);
		}
	}
	uint64_t gva = ok ? sweet_gpu_vm_map(pa, npages, false) : 0;
	if (gva == 0) {
		if (pa != NULL) {
			IOFreeData(pa, npages * sizeof(uint64_t));
		}
		md->complete();
		s->release();
		return kIOReturnNoMemory;
	}
	md->retain();
	*b = (struct sweet_gpu_bo){ .iova = gva, .size = size, .md = md, .surface = s, .pa = pa, .npages = npages };
	out[0] = handle;
	out[1] = gva;
	out[2] = size;
	return kIOReturnSuccess;
}

/* Lock held. in: struct sweet_gpu_submit, ibs, handles. */
IOReturn
SweetGPUUserClient::submit(const void *in, size_t len, uint64_t *seqOut)
{
	struct sweet_gpu_submit h;
	if (len < sizeof(h)) {
		return kIOReturnBadArgument;
	}
	memcpy(&h, in, sizeof(h));
	if (h.nr_ibs == 0 || h.nr_ibs > SWEET_GPU_MAX_IBS || h.nr_bos > SWEET_GPU_MAX_BOS ||
	    len != sizeof(h) + h.nr_ibs * sizeof(struct sweet_gpu_ib) + h.nr_bos * sizeof(uint32_t)) {
		return kIOReturnBadArgument;
	}
	const struct sweet_gpu_ib *ib = (const struct sweet_gpu_ib *)((const char *)in + sizeof(h));
	const uint32_t *handles = (const uint32_t *)(ib + h.nr_ibs);
	for (uint32_t i = 0; i < h.nr_bos; i++) {
		struct sweet_gpu_bo *b = bo(handles[i]);
		if (b == NULL) {
			return kIOReturnBadArgument;
		}
		/*
		 * CPU-cached: its CPU writes to memory, no stale lines over GPU
		 * writes. Only pages written since the last submit: flushing every
		 * page of every listed bo was ~1/4 of backboardd's CPU (0182g).
		 */
		for (uint32_t p = 0; p < b->npages; p++) {
			flush_if_written(b->pa[p]);
		}
	}
	uint32_t seq = 0;
	int e = sweet_gpu_submit(ib, h.nr_ibs, &seq);
	if (e != 0) {
		return e == EFAULT ? kIOReturnNotPermitted : e == EINVAL ? kIOReturnBadArgument :
		       e == ETIMEDOUT ? kIOReturnTimeout : kIOReturnNotReady;
	}
	for (uint32_t i = 0; i < h.nr_bos; i++) {
		struct sweet_gpu_bo *b = bo(handles[i]);
		b->last_seq = seq;
		b->used = true;
	}
	*seqOut = seq;
	return kIOReturnSuccess;
}

IOReturn
SweetGPUUserClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
    __unused IOExternalMethodDispatch *dispatch, __unused OSObject *target, __unused void *reference)
{
	if (selector == 14) {           /* wait: without the client lock (other threads submit) */
		if (args->scalarInputCount != 2) {
			return kIOReturnBadArgument;
		}
		int e = sweet_gpu_wait((uint32_t)args->scalarInput[0], (uint32_t)(args->scalarInput[1] < 60000 ? args->scalarInput[1] : 60000));
		return e == 0 ? kIOReturnSuccess : e == ETIMEDOUT ? kIOReturnTimeout : kIOReturnNotReady;
	}
	if (!sweet_gpu_ready()) {
		return kIOReturnNotReady;
	}
	IOReturn ret = kIOReturnBadArgument;
	IOLockLock(fLock);
	switch (selector) {
	case 10:                /* bo new */
		if (args->scalarInputCount >= 1 && args->scalarOutputCount >= 3) {
			ret = boNew(args->scalarInput[0], args->scalarOutput);
			args->scalarOutputCount = ret == kIOReturnSuccess ? 3 : 0;
		}
		break;
	case 11:                /* bo free */
		if (args->scalarInputCount == 1) {
			struct sweet_gpu_bo *b = bo(args->scalarInput[0]);
			ret = b != NULL ? kIOReturnSuccess : kIOReturnNotFound;
			if (b != NULL) {
				freeBo(b);
			}
		}
		break;
	case 12:                /* bo import */
		if (args->scalarInputCount == 1 && args->scalarOutputCount >= 3) {
			ret = boImport((uint32_t)args->scalarInput[0], args->scalarOutput);
			args->scalarOutputCount = ret == kIOReturnSuccess ? 3 : 0;
		}
		break;
	case 13:                /* submit */
		if (args->scalarOutputCount >= 1) {
			uint64_t seq = 0;
			if (args->structureInputDescriptor != NULL) {
				IOMemoryDescriptor *d = args->structureInputDescriptor;
				size_t len = d->getLength();
				void *buf = len <= (1u << 20) ? IOMallocData(len) : NULL;
				if (buf == NULL) {
					ret = kIOReturnNoMemory;
					break;
				}
				ret = d->prepare() == kIOReturnSuccess ? kIOReturnSuccess : kIOReturnVMError;
				if (ret == kIOReturnSuccess) {
					ret = d->readBytes(0, buf, len) == len ? submit(buf, len, &seq) : kIOReturnVMError;
					d->complete();
				}
				IOFreeData(buf, len);
			} else if (args->structureInput != NULL) {
				ret = submit(args->structureInput, args->structureInputSize, &seq);
			}
			args->scalarOutput[0] = seq;
			args->scalarOutputCount = 1;
		}
		break;
	case 15:                /* info */
		if (args->scalarOutputCount >= 5) {
			struct sweet_gpu_info info;
			sweet_gpu_get_info(&info);
			args->scalarOutput[0] = info.chip_id;
			args->scalarOutput[1] = info.gmem_size;
			args->scalarOutput[2] = info.gmem_base;
			args->scalarOutput[3] = info.max_freq;
			args->scalarOutput[4] = 0;      /* fence page no longer mapped: poll with 14 */
			args->scalarOutputCount = 5;
			ret = kIOReturnSuccess;
		}
		break;
	case 16:                /* bo cpu prep */
		if (args->scalarInputCount == 1) {
			struct sweet_gpu_bo *b = bo(args->scalarInput[0]);
			ret = b == NULL ? kIOReturnNotFound :
			    b->used && sweet_gpu_wait(b->last_seq, 0) != 0 ? kIOReturnBusy : kIOReturnSuccess;
			for (uint32_t p = 0; ret == kIOReturnSuccess && p < b->npages; p++) {
				flush_dcache64((addr64_t)b->pa[p], PAGE_SIZE, TRUE);
			}
		}
		break;

	case 0:                 /* map user memory */
		if ((args->scalarInputCount == 2 || args->scalarInputCount == 3) && args->scalarOutputCount >= 1) {
			uint64_t addr = args->scalarInput[0], len = args->scalarInput[1];
			bool ro = args->scalarInputCount == 3 && (args->scalarInput[2] & 1);
			uint64_t base = trunc_page_64(addr), end = round_page_64(addr + len);
			if (len == 0 || end <= base || end - base > SWEET_GPU_MAX_MAP_BYTES) {
				break;
			}
			IOMemoryDescriptor *md = IOMemoryDescriptor::withAddressRange(base, end - base,
			    ro ? kIODirectionOut : kIODirectionInOut, fTask);
			if (md == NULL) {
				ret = kIOReturnNoMemory;
				break;
			}
			uint64_t gva = 0;
			ret = mapDescriptor(md, addr - base, len, NULL, ro, &gva);
			if (ret != kIOReturnSuccess) {
				md->release();
				break;
			}
			args->scalarOutput[0] = gva;
			args->scalarOutputCount = 1;
		}
		break;
	case 1:                 /* map IOSurface */
		if (args->scalarInputCount == 1 && args->scalarOutputCount >= 2) {
			MidoSurface *s = mido_surface_copy((uint32_t)args->scalarInput[0]);
			if (s == NULL || s->memory == NULL) {
				OSSafeReleaseNULL(s);
				ret = kIOReturnNotFound;
				break;
			}
			s->memory->retain();
			uint64_t gva = 0;
			ret = mapDescriptor(s->memory, 0, s->memory->getLength(), s, false, &gva);
			if (ret != kIOReturnSuccess) {
				s->memory->release();
				s->release();
				break;
			}
			args->scalarOutput[0] = gva;
			args->scalarOutput[1] = s->allocSize;
			args->scalarOutputCount = 2;
		}
		break;
	case 2:                 /* unmap */
		if (args->scalarInputCount == 1) {
			ret = kIOReturnNotFound;
			for (unsigned i = 0; i < SWEET_GPU_MAX_MAPS; i++) {
				if (fMaps[i].md != NULL && fMaps[i].start == args->scalarInput[0]) {
					unmapSlot(i);
					ret = kIOReturnSuccess;
					break;
				}
			}
		}
		break;
	case 3:                 /* quad */
		if (args->structureInputSize == sizeof(struct sweet_gpu_quad) && args->structureInput != NULL) {
			struct sweet_gpu_quad q;
			memcpy(&q, args->structureInput, sizeof(q));
			if (!owns(q.src_va, (uint64_t)q.src_pitch * q.src_h) ||
			    !owns(q.dst_va, (uint64_t)q.dst_pitch * q.dst_h)) {
				ret = kIOReturnNotPermitted;
				break;
			}
			int e = sweet_gpu_quad(&q);
			ret = e == 0 ? kIOReturnSuccess : e == ETIMEDOUT ? kIOReturnTimeout :
			    e == EFAULT ? kIOReturnNotPermitted : e == ENXIO ? kIOReturnNotReady : kIOReturnBadArgument;
		}
		break;
	default:
		ret = kIOReturnUnsupported;
		break;
	}
	IOLockUnlock(fLock);
	return ret;
}
#endif /* MIDO */
