#!/usr/bin/env python2
##
##  mk10646.py - compose multiple .bdf fonts to one ISO-10646 font.
##  (Python2 only)
##
##  by Yusuke Shinyama
##  *public domain*
##
##  Usage: $ python mk10646.py input1.bdf input2.bdf ... > output.bdf
##
##  Note: when there are multiple glyphs for the same character,
##        the first glyph is used.
##

import sys


# convert JISX0201 code to UCS (maybe not entirely correct)
def jisx0201toucs(x):
    return ord(chr(x).decode('cp932'))

# convert JISX0208 code to UCS (maybe not entirely correct)
def jisx0208toucs(x):
    return ord(('\x1b$B'+chr(x//256)+chr(x%256)+'\x1b(B').decode('iso-2022-jp'))

# wide chars
CHARWIDTH = {}
def load_charwidth(path):
    fp = open(path, 'r')
    for line in fp:
        (line,_,_) = line.partition('#')
        line = line.strip()
        if not line: continue
        (rng,_,wid) = line.partition(';')
        (b,_,e) = rng.partition('..')
        if not e:
            e = b
        b = int(b, 16)
        e = int(e, 16)
        for c in xrange(b, e+1):
            CHARWIDTH[c] = wid
    fp.close()

# shrink_bits
def shrink_bits(bits):
    a = ''
    x0 = None
    for b in bits:
        b = ord(b)
        x1 = 0
        if b & 0xc0:
            x1 |= 0x8
        if b & 0x30:
            x1 |= 0x4
        if b & 0x0c:
            x1 |= 0x2
        if b & 0x03:
            x1 |= 0x1
        if x0 is not None:
            a += chr(x0 << 4 | x1)
            x0 = None
        else:
            x0 = x1
    if x0 is not None:
        a += chr(x0 << 4)
    return a

# expand_bits
def expand_bits(bits):
    a = ''
    for b in bits:
        b = ord(b)
        for i in (b >> 4, b & 0xf):
            x = 0
            if b & 8:
                x |= 0xc0
            if b & 4:
                x |= 0x30
            if b & 2:
                x |= 0x0c
            if b & 1:
                x |= 0x03
            a += chr(x)
    return a


##  BDFParserBase
##
class BDFParserBase(object):

    def feed(self, line):
        (cmd,_,args) = line.partition(' ')
        attr = 'do_'+cmd.lower()
        if hasattr(self, attr):
            func = getattr(self, attr)
            func(args)
        else:
            self.do_unknown(cmd, args)
        return

    def do_unknown(self, cmd, args):
        raise ValueError('unknown command: %r' % cmd)


##  BDFGlyphParser
##
class BDFGlyphParser(BDFParserBase):

    def __init__(self, name):
        self.name = name
        self.encoding = None
        self.swidth = None
        self.dwidth = None
        self.bbx = None
        self.wide = False
        self.bits = []
        self.changed = False
        self._bitmap = False
        return

    def __repr__(self):
        return '<Glyph: %r>' % self.encoding

    def feed(self, line):
        (cmd,_,args) = line.strip().partition(' ')
        if self._bitmap:
            self.bits.append(line)
        else:
            BDFParserBase.feed(self, line)
        return

    def do_bitmap(self, args):
        assert not self._bitmap
        self._bitmap = True
        return

    def do_encoding(self, args):
        self.encoding = int(args)
        return
    
    def do_swidth(self, args):
        self.swidth = map(int, args.split(' '))
        return
    
    def do_dwidth(self, args):
        self.dwidth = map(int, args.split(' '))
        return
    
    def do_bbx(self, args):
        self.bbx = map(int, args.split(' '))
        self.wide = (self.bbx[0] == self.bbx[1])
        return
    
    def finish(self):
        self._bitmap = False
        return

    def adjust(self, wide=False):
        if self.wide and not wide:
            self.swidth[0] = self.swidth[0]//2
            self.dwidth[0] = self.dwidth[0]//2
            self.bbx[0] = self.bbx[0]//2
            self.bits = [ shrink_bits(bit.decode('hex')).encode('hex')
                          for bit in self.bits ]
        elif not self.wide and wide:
            self.swidth[0] = self.swidth[0]*2
            self.dwidth[0] = self.dwidth[0]*2
            self.bbx[0] = self.bbx[0]*2
            self.bits = [ expand_bits(bit.decode('hex')).encode('hex')
                          for bit in self.bits ]
        self.changed = True
        self.wide = wide
        return

    def dump(self, fp, encoding):
        assert self.name is not None
        assert self.swidth is not None
        assert self.dwidth is not None
        assert self.bbx is not None
        fp.write('STARTCHAR %s\n' % self.name)
        fp.write('ENCODING %r\n' % encoding)
        fp.write('SWIDTH %s\n' % ' '.join(map(str, self.swidth)))
        fp.write('DWIDTH %s\n' % ' '.join(map(str, self.dwidth)))
        fp.write('BBX %s\n' % ' '.join(map(str, self.bbx)))
        fp.write('BITMAP\n')
        for bit in self.bits:
            fp.write(bit+'\n')
        fp.write('ENDCHAR\n')
        return


##  BDFFileParser
##
class BDFFileParser(BDFParserBase):

    def __init__(self, src):
        self.src = src
        self.version = None
        self.name = None
        self.size = None
        self.bbx = None
        self.props = None
        self.comments = []
        self.glyphs = []
        self._prop = False
        self._glyph = None
        return
    
    def feed(self, line):
        if self._glyph is not None:
            if line.lower() == 'endchar':
                self._glyph.finish()
                self.do_endchar()
            else:
                self._glyph.feed(line)
        else:
            BDFParserBase.feed(self, line)
        return

    def do_startfont(self, args):
        assert self.version is None
        self.version = args
        return
    
    def do_endfont(self, args):
        return
    
    def do_comment(self, args):
        self.comments.append(args)
        return
    
    def do_font(self, args):
        assert self.name is None
        self.name = args
        return
    
    def do_size(self, args):
        assert self.size is None
        self.size = args
        return
    
    def do_fontboundingbox(self, args):
        assert self.bbx is None
        self.bbx = args.split(' ')
        return
    
    def do_startproperties(self, args):
        assert self.props is None
        assert not self._prop
        self.props = []
        self._prop = True
        return
    
    def do_endproperties(self, args):
        assert self.props is not None
        assert self._prop
        self._prop = False
        return

    def do_chars(self, args):
        return
    
    def do_unknown(self, cmd, args):
        if self._prop:
            assert cmd not in self.props
            attr = 'prop_'+cmd.lower()
            if hasattr(self, attr):
                func = getattr(self, attr)
                func(cmd.lower(), args)
            else:
                self.prop_unknown(cmd, args)
        else:
            BDFParserBase.do_unknown(self, cmd, args)
        return

    def do_startchar(self, args):
        self._glyph = BDFGlyphParser(args)
        return
        
    def do_endchar(self):
        self.glyphs.append(self._glyph)
        self._glyph = None
        return

    def _parse_str(self, k, v):
        assert v.startswith('"')
        assert v.endswith('"')
        self.props.append((k, v[1:-1]))
        return

    def _parse_int(self, k, v):
        self.props.append((k, int(v)))
        return

    prop_font_ascent = _parse_int
    prop_font_descent = _parse_int
    prop_copyright = _parse_str
    prop_fontname_registry = _parse_str
    prop_foundry = _parse_str
    prop_family_name = _parse_str
    prop_weight_name = _parse_str
    prop_slant = _parse_str
    prop_setwidth_name = _parse_str
    prop_add_style_name = _parse_str
    prop_pixel_size = _parse_int
    prop_point_size = _parse_int
    prop_resolution_x = _parse_int
    prop_resolution_y = _parse_int
    prop_spacing = _parse_str
    prop_average_width = _parse_int
    prop_charset_registry = _parse_str
    prop_charset_encoding = _parse_str
    prop_default_char = _parse_int

    def prop_unknown(self, k, v):
        raise ValueError('unknown prop: %r' % k)

    def get_prop(self, k0):
        for (k,v) in self.props:
            if k.lower() == k0.lower():
                return v
        raise KeyError(k0)

    def set_prop(self, k0, v):
        for (i,(k,_)) in enumerate(self.props):
            if k.lower() == k0.lower():
                self.props[i] = (k,v)
                return
        raise KeyError(k0)

    def dump_header(self, fp):
        assert self.version is not None
        assert self.name is not None
        assert self.size is not None
        assert self.bbx is not None
        fp.write('STARTFONT %s\n' % self.version)
        for comment in self.comments:
            fp.write('COMMENT %s\n' % comment)
        name = ('%s-%s-%s-%s-%s-%s-%s-%s-%s-%s-%s-%s-%s-%s-%s' % 
                (self.get_prop('FONTNAME_REGISTRY'),
                 self.get_prop('FOUNDRY'),
                 self.get_prop('FAMILY_NAME'),
                 self.get_prop('WEIGHT_NAME'),
                 self.get_prop('SLANT'),
                 self.get_prop('SETWIDTH_NAME'),
                 self.get_prop('ADD_STYLE_NAME'),
                 self.get_prop('PIXEL_SIZE'),
                 self.get_prop('POINT_SIZE'),
                 self.get_prop('RESOLUTION_X'),
                 self.get_prop('RESOLUTION_Y'),
                 self.get_prop('SPACING'),
                 self.get_prop('AVERAGE_WIDTH'),
                 self.get_prop('CHARSET_REGISTRY'),
                 self.get_prop('CHARSET_ENCODING')))
        fp.write('FONT %s\n' % name)
        fp.write('SIZE %s\n' % self.size)
        fp.write('FONTBOUNDINGBOX %s\n' % ' '.join(self.bbx))
        fp.write('STARTPROPERTIES %r\n' % len(self.props))
        for (k,v) in self.props:
            if isinstance(v, str):
                v = '"%s"' % v
            fp.write('%s %s\n' % (k.upper(), v))
        fp.write('ENDPROPERTIES\n')
        return

    def dump_footer(self, fp):
        fp.write('ENDFONT\n')
        return

# main
def main(argv):
    import fileinput
    args = argv[1:]
    out = sys.stdout
    glyphs = {}
    parser = None
    ambwide = False
    load_charwidth('EastAsianWidth.txt')
    for path in args:
        print >>sys.stderr, 'reading: %r' % path
        parser = BDFFileParser(path)
        fp = open(path, 'r')
        for line in fp:
            parser.feed(line.strip())
        fp.close()
        codec = (parser.get_prop('CHARSET_REGISTRY')+'-'+
                 parser.get_prop('CHARSET_ENCODING'))
        if codec.startswith('JISX0201'):
            f = jisx0201toucs
        elif codec.startswith('JISX0208'):
            f = jisx0208toucs
        else:
            try:
                ''.decode(codec)
            except UnicodeError:
                raise ValueError('unknown charset: %r' % codec)
            f = (lambda x: ord(chr(x).decode(codec)))
        # convert each charcode to UCS/Unicode.
        for glyph in parser.glyphs:
            e = f(glyph.encoding)
            if e in glyphs:
                glyphs[e].append(glyph)
            else:
                glyphs[e] = [glyph]
    # use the properties from the last file.
    assert parser is not None
    parser.set_prop('CHARSET_REGISTRY', 'ISO10646')
    parser.set_prop('CHARSET_ENCODING', '1')
    parser.dump_header(out)
    out.write('CHARS %r\n' % len(glyphs))
    for e in sorted(glyphs):
        wid = CHARWIDTH.get(e)
        for glyph in glyphs[e]:
            ok = True
            if (wid == 'F' or wid == 'W'):
                ok = glyph.wide
            elif (wid == 'H' or wid == 'Na'):
                ok = not glyph.wide
            elif wid == 'A':
                ok = (glyph.wide == ambwide)
            if ok:
                glyph.dump(out, encoding=e)
                break
        else:
            print >>sys.stderr, 'warning: invalid width: U+%04x (%s:%r)' % (e, wid, glyph.wide)
            glyph.adjust(wide=(wid in ('F','W')))
            glyph.dump(out, encoding=e)
    parser.dump_footer(out)
    return 0

if __name__ == '__main__': sys.exit(main(sys.argv))
