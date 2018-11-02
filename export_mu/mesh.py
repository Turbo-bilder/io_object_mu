# vim:ts=4:et
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

import bpy
from mathutils import Vector

from ..mu import MuMesh, MuRenderer
from ..utils import collect_modifiers

from .material import make_material

from . import export

def split_face(mesh, index):
    face = mesh.polygons[index]
    s, e = face.loop_start, face.loop_start + face.loop_total
    # extract up to two uv layers from the mesh
    uv = list(map(lambda layer:
                  list(map(lambda a:
                           a.uv,
                           layer.data[s:e])),
                  mesh.uv_layers[:2]))
    fv = list(face.vertices)
    tris = []
    for i in range(1, len(fv) - 1):
        tri = ((fv[0], tuple(map(lambda l: tuple(l[0]), uv))),
               (fv[i], tuple(map(lambda l: tuple(l[i]), uv))),
               (fv[i+1], tuple(map(lambda l: tuple(l[i+1]), uv))))
        tris.append(tri)
    return tris

def build_submeshes(mesh):
    submeshes = []
    submesh = []
    for i in range(len(mesh.polygons)):
        submesh.append(i)
    submeshes.append(submesh)
    return submeshes

def make_tris(mesh, submeshes):
    for sm in submeshes:
        i = 0
        while i < len(sm):
            tris = split_face(mesh, sm[i])
            sm[i:i+1] = tris
            i += len(tris)
    return submeshes

def make_verts(mesh, submeshes):
    verts = []
    normals = []
    uvs = []
    groups = []
    for sm in submeshes:
        vuvdict = {}
        for i, ft in enumerate(sm):
            tv = []
            for vuv in ft:
                if vuv not in vuvdict:
                    vuvdict[vuv] = len(verts)
                    mv = mesh.vertices[vuv[0]]
                    verts.append(tuple(mv.co))
                    normals.append(tuple(mv.normal))
                    uvs.append(vuv[1])
                    groups.append(mv.groups)
                tv.append(vuvdict[vuv])
            sm[i] = tv
    return verts, uvs, normals, groups

def make_tangents(verts, uvs, normals, submeshes):
    sdir = [Vector()] * len(verts)
    tdir = [Vector()] * len(verts)
    tangents = []
    for sm in submeshes:
        for tri in sm:
            v1 = Vector(verts[tri[0]])
            v2 = Vector(verts[tri[1]])
            v3 = Vector(verts[tri[2]])

            w1 = uvs[tri[0]]
            w2 = uvs[tri[1]]
            w3 = uvs[tri[2]]

            u1 = v2 - v1
            u2 = v3 - v1

            s1 = w2[0] - w1[0]
            s2 = w3[0] - w1[0]
            t1 = w2[1] - w1[1]
            t2 = w3[1] - w1[1]

            r = s1 * t2 - s2 * t1

            if r * r < 1e-6:
                continue
            sd = (t2 * u1 - t1 * u2) / r
            td = (s1 * u2 - s2 * u1) / r

            sdir[tri[0]] += sd
            sdir[tri[1]] += sd
            sdir[tri[2]] += sd
            tdir[tri[0]] += td
            tdir[tri[1]] += td
            tdir[tri[2]] += td
    for i, n in enumerate(normals):
        t = sdir[i]
        t -= t.dot(n) * Vector(n)
        t.normalize()
        hand = t.dot(tdir[i]) < 0 and -1.0 or 1.0
        tangents.append(tuple(t) + (hand,))
    return tangents

def make_mesh(mu, obj):
    #FIXME mesh = obj.to_mesh(bpy.context.scene, True, 'RENDER')
    modifiers = collect_modifiers(obj)
    for mod in modifiers:
        mod.show_viewport = False
    mesh = obj.to_mesh(bpy.context.depsgraph, True)
    for mod in modifiers:
        mod.show_viewport = True
    submeshes = build_submeshes(mesh)
    submeshes = make_tris(mesh, submeshes)
    mumesh = MuMesh()
    vun = make_verts(mesh, submeshes)
    mumesh.verts, uvs, mumesh.normals, mesh.groups = vun
    if uvs:
        if len(uvs) > 0:
            mumesh.uvs = list(map(lambda uv: uv[0], uvs))
        if len(uvs) > 1:
            mumesh.uv2s = list(map(lambda uv: uv[1], uvs))
    mumesh.submeshes = submeshes
    if mumesh.uvs:
        mumesh.tangents = make_tangents(mumesh.verts, mumesh.uvs,
                                        mumesh.normals, mumesh.submeshes)
    return mumesh

def mesh_materials(mu, mesh):
    materials = []
    for mat in mesh.materials:
        if mat.mumatprop.shaderName:
            if mat.name not in mu.materials:
                mu.materials[mat.name] = make_material(mu, mat)
            materials.append(mu.materials[mat.name].index)

def make_renderer(mu, mesh):
    rend = MuRenderer()
    #FIXME shadows
    rend.materials = mesh_materials(mu, mesh)
    if not rend.materials:
        return None
    return rend

def mesh_bones(obj, mumesh, armature):
    boneset = set()
    for bone in armature:
        boneset.add(bone.name)
    bones = []
    boneindices = {}
    for grp in obj.vertex_groups:
        if grp.name in boneset:
            boneindices[grp.name] = len(bones)
            bones.append(grp.name)
    for vgrp in mumesh.groups:
        weights = []
        for i in len(vgrp):
            gname = obj.vertex_groups[vgrp[i].group].name 
            if gname in boneindices:
                weights.append((boneindices[gname], vgrp[i].weight))
        weights.sort(key=lambda w: w[1])
        weights.reverse()
        if len(weights) < 4:
            weights += [(0,0)]*4 - len(weights)
        print(weights)
    return bones

def handle_mesh(obj, muobj, mu):
    muobj.shared_mesh = make_mesh(mu, obj)
    muobj.renderer = make_renderer(mu, obj.data)
    return muobj

def handle_skinned_mesh(obj, muobj, mu, armature):
    smr = MuSkinnedMeshRenderer()
    smr.mesh = make_mesh(mu, obj)
    smr.bones = mesh_bones(obj, smr.mesh, armature)
    smr.materials = mesh_materials(mu, obj.data)
    #FIXME center, size, quality, updateWhenOffscreen
    muobj.skinned_mesh_renderer = smr
    if hasattr(muobj, "renderer"):
        delattr(muobj, "renderer")
    if hasattr(muobj, "shared_mesh"):
        delattr(muobj, "shared_mesh")
    return muobj

type_handlers = {
    bpy.types.Mesh: handle_mesh,
}